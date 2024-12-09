import os
import json
from glob import glob
from llama_index.core.indices import MultiModalVectorStoreIndex

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
from llama_index.core.vector_stores.simple import SimpleVectorStore
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.vector_stores.qdrant import QdrantVectorStore

from llama_index.core.schema import ImageNode

from llama_index.multi_modal_llms.openai import OpenAIMultiModal

import qdrant_client
from tinydb import TinyDB, Query


class VideoRag:
    _query_prompt = (
    "Given the provided information, including relevant images and retrieved context from the video which represents an event, \
 accurately and precisely answer the query without any additional prior knowledge.\n"
    "---------------------\n"
    "Context: {context_str}\n"
    "Additional context for event that the video represents.: {event_metadata} \n"
    "---------------------\n"
    "Query: {query_str}\n"
    "Answer: "
    )
    def __init__(self, data_path, storage_path = '', text_storage_path = '', text_tsindex_dirpath = None, image_tsindex_dirpath = None, use_qdrant=True):
        self.data_path = data_path
        self.use_qdrant = use_qdrant
        self.text_tsindex_dirpath = text_tsindex_dirpath
        self.image_tsindex_dirpath = image_tsindex_dirpath
        self.storage_path = storage_path
        self.text_storage_path = text_storage_path
    
    def create_ts_index(self):
        if self.text_tsindex_dirpath:
            text_index_paths = glob(self.text_tsindex_dirpath+'/*_text_tsindex.json')
            text_index_agg_path = os.path.join(self.text_tsindex_dirpath, 'text_tsindex.json')
            
            if os.path.exists(text_index_agg_path):
                print(f"Removing placeholder text index file: {text_index_agg_path}")
                os.remove(text_index_agg_path)

            self.text_tsindex = TinyDB(text_index_agg_path)
            for path in text_index_paths:
                with open(path) as f:
                    self.text_tsindex.insert_multiple(documents=json.load(f)['_default'].values())

        if self.image_tsindex_dirpath:
            img_index_paths = glob(self.image_tsindex_dirpath+'/*_image_tsindex.json')
            img_index_agg_path = os.path.join(self.image_tsindex_dirpath, 'image_tsindex.json')
  
            if os.path.exists(img_index_agg_path):
                print(f"Removing placeholder image index file: {img_index_agg_path}")
                os.remove(img_index_agg_path)
  
            self.image_tsindex  = TinyDB(img_index_agg_path)
            self.ImageDoc = Query()
            
            for path in img_index_paths:
                with open(path) as f:
                    self.image_tsindex.insert_multiple(documents=json.load(f)['_default'].values())
    
    def create_vector_index(self, documents=None):
        if self.use_qdrant:
            # Create a local Qdrant vector store
            lock_fpath = os.path.join(self.storage_path, '.lock')
            print(f"Lock file is located at {lock_fpath}")
            print(os.listdir(self.storage_path))
            if os.path.exists(lock_fpath):
                print(f"Removing lock file: {lock_fpath}")
                os.remove(lock_fpath)
            self.qdrant_client = qdrant_client.QdrantClient(path=self.storage_path)

            self.text_store = QdrantVectorStore(client=self.qdrant_client, collection_name="text_collection")
            self.image_store = QdrantVectorStore(client=self.qdrant_client, collection_name="image_collection")
        else:
            self.text_store = LanceDBVectorStore(uri="lancedb", table_name="text_collection")
            self.image_store = LanceDBVectorStore(uri="lancedb", table_name="image_collection")
        
        doc_store_path = os.path.join(self.storage_path, 'docstore.json')
        if os.path.exists(doc_store_path):
            print(f"Loading index from storage: {self.storage_path}")
            storage_context = StorageContext.from_defaults(vector_store=self.text_store, image_store=self.image_store, persist_dir=self.storage_path)
            self.index = load_index_from_storage(storage_context)
            if documents is not None:
                self.add_documents(self.index, self.storage_path, documents)
        else:
            # Create an empty vector store
            if documents is None and os.path.exists(self.data_path):
                print(f"Creating a new index from the data in {self.data_path}")
                documents = SimpleDirectoryReader(self.data_path, recursive=True).load_data()
            else:
                documents = documents or []
                print(f"Creating a new index from the documents: {len(documents)}")
            storage_context = StorageContext.from_defaults(vector_store=self.text_store, image_store=self.image_store)
            self.index = MultiModalVectorStoreIndex.from_documents(documents, storage_context=storage_context)
            self.index.storage_context.persist(persist_dir=self.storage_path)

        if os.path.exists(self.text_storage_path):
            print(f"Loading text index from storage: {self.text_storage_path}")
            text_storage_context = StorageContext.from_defaults(persist_dir=self.text_storage_path)
            self.text_index = load_index_from_storage(text_storage_context)
            if documents is not None:
                self.add_documents(self.text_index, self.text_storage_path, documents)
        else:
            if documents is None and os.path.exists(self.data_path):
                print(f"Creating a new text index from the data in {self.data_path}")
                documents = SimpleDirectoryReader(input_dir=self.data_path, required_exts = [".txt"], recursive=True).load_data()
            else:
                documents = documents or []
                print(f"Creating a new text index from the documents: {len(documents)}")
            # Create an empty vector store
            vector_store = SimpleVectorStore()
            # Create a storage context with the empty vector store
            text_storage_context = StorageContext.from_defaults(vector_store=vector_store)
            # Create an empty VectorStoreIndex
            self.text_index = VectorStoreIndex.from_documents(documents, storage_context=text_storage_context)
            self.text_index.storage_context.persist(persist_dir=self.text_storage_path)


        self.retriever_engine = self.index.as_retriever(similarity_top_k=5, image_similarity_top_k=5)
        self.text_retriever_engine = self.text_index.as_retriever(retrieval_mode='similarity', k=5)

    def add_documents(self, index, storage_path, documents):
        index.refresh_ref_docs(documents)
        index.storage_context.persist(persist_dir=storage_path)

    def add_document(self, index, storage_path, document):
        index.insert(document)
        index.storage_context.persist(persist_dir=storage_path)

    def count_documents(self):
        return len(self.index.vector_store.get_nodes())

    def count_text_documents(self):
        return len(self.text_index.docstore.docs)

    def print_text_tsindex(self):
        if self.text_tsindex:
            all_records = self.text_tsindex.all()
            print(f"Number of records = f{len(all_records)}")
            print("-----------")
            print(all_records)
        else:
            print("Text ts index doesn't exist.")

    def print_image_tsindex(self):
        if self.image_tsindex:
            all_records = self.image_tsindex.all()
            print(f"Number of records = f{len(all_records)}")
            print("-----------")
            print(all_records)
        else:
            print("Image ts index doesn't exist.")

    def image_search(self, search_path):
        return self.image_tsindex.search(self.ImageDoc.frame_path.matches(f'.*{search_path}'))[0]['timestamp']
    
    def retrieve_internal(self, retriever_engine, query_str):
        retrieval_results = retriever_engine.retrieve(query_str)

        retrieved_image = []
        retrieved_text = []
        for res_node in retrieval_results:
            if isinstance(res_node.node, ImageNode):
                retrieved_image.append(res_node.node.metadata["file_path"])
            else:
                retrieved_text.append(res_node.text)

        return retrieved_image, retrieved_text 

    def retrieve_internal_2(self, retriever_engine, query_str):
        return retriever_engine.retrieve(query_str)

    def query_internal(self, query_str):
        return self.retrieve_internal(self.retriever_engine, query_str)

    def retrieve(self, query_str):
        img, txt = self.retrieve_internal(retriever_engine=self.retriever_engine, query_str=query_str)
        image_documents = SimpleDirectoryReader(input_dir=self.data_path, input_files=img).load_data() if img else []
        context_str = "".join(txt)
        return context_str, image_documents
    
    def init_multimodal_oai(self):
        self.openai_mm_llm = OpenAIMultiModal(model="gpt-4o", max_new_tokens=1500)

    def query_with_oai(self, query_str, context, img):
        text_response = self.openai_mm_llm.complete(prompt=VideoRag._query_prompt.format(
            context_str=context, query_str=query_str, event_metadata=""), image_documents=img)

        print(text_response.text)
        return text_response.text

    def cleanup(self):
        self.qdrant_client.close()

