# Process a video by extracting knowledge from it into a rag.
# Currently just converts into a text file.

from pytubefix import YouTube
from pytubefix.cli import on_progress
from pathlib import Path
from moviepy.editor import VideoFileClip
import speech_recognition as sr
import random
import string
import os
import re
import argparse
from video_index.video_processing.frame_diff import OpenCVFrameWriter
from video_index.video_processing.whisper_turbo import WhisperTurbo

def replace_non_alphanumeric(input_string, rep_string):
    # Replace all non-alphabetic and non-numeric characters with a space
    return re.sub(r'[^a-zA-Z0-9]', rep_string, input_string)

def generate_random_string(length):
    # Generate a random string of specified length using letters and digits
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choice(characters) for _ in range(length))
    return random_string

def generate_filename(title, random_str, ext="mp4"):
    title_0 = replace_non_alphanumeric(title, "_")
    title_1=  '_'.join(title_0.strip().split())
    return f"{title_1}_{random_str}.{ext}"

def generate_subtitlesfilename(title, random_str):
    title_0 = replace_non_alphanumeric(title, "_")
    title_1=  '_'.join(title_0.strip().split())
    return f"{title_1}_{random_str}_subtitles.srt"

def get_audio_outfile(video_outfile, ext="mp4"):
    return video_outfile.replace(ext, "wav")

def get_text_outfile(video_outfile, ext="mp4"):
    return video_outfile.replace(ext, "txt")  

def make_tempdirs(folder_path):
    Path(folder_path).mkdir(parents=True, exist_ok=True)

def get_file_parts(file):
    """
    Get the file name and extension of a file.

    Returns:
        (file_name, file_extension)
    """
    file_parts = os.path.splitext(file.name)
    return file_parts[0].lower(), file_parts[1].lower()[1:]

class Video:
    _example_video_url = "https://www.youtube.com/watch?v=d_qvLDhkg00"
    _example_output_folder = "./temp/video_data/"

    def __init__(self, url, video_filepath):
        self.url = url
        self.video_filepath = video_filepath
        self.file_prefix = Path(self.video_filepath).stem
        self.audio_filepath = ""
        self.text_filepath = ""
    
    @classmethod
    def from_url(cls, url):
        return cls(url, "")
    
    @classmethod
    def from_file(cls, video_filepath):
        return cls("", video_filepath)

    def _download_video(self, output_path):
        """
        Download a video from a given url and save it to the output path.

        Parameters:
        url (str): The url of the video to download.
        output_path (str): The path to save the video to.

        Returns:
        dict: A dictionary containing the metadata of the video.
        """

        yt = YouTube(self.url, 'ANDROID', on_progress_callback=on_progress)
        metadata = {"Author": yt.author, "Title": yt.title, "Views": yt.views}
        rnd_str = generate_random_string(10)
        outfilename = generate_filename(yt.title, rnd_str)
        print(f"Saving video as {outfilename}")
        yt.streams.get_highest_resolution().download(
            output_path=output_path, filename=outfilename
        )
        subtitles_outfile = generate_subtitlesfilename(yt.title, rnd_str)
        if subtitles_outfile is not None:
            caption = yt.captions.get_by_language_code('en')
            if caption is not None:
                caption.save_captions(subtitles_outfile)
        return (metadata, outfilename)


    def extract_audio(self, output_audio_path):
        """
        Convert a video to audio and save it to the output path.

        Parameters:
        video_path (str): The path to the video file.
        output_audio_path (str): The path to save the audio to.

        """
        print("Extracting audio ..")
        clip = VideoFileClip(self.video_filepath)
        audio = clip.audio
        audio.write_audiofile(output_audio_path)
        self.audio_filepath = output_audio_path


    def extract_images_with_index(self, eventkb_output_path):
        """
           Convert a video to a sequence of images and save them to the output folder. Uses a diff threshold strategy.
           Outputs to an image subfolder within 'eventkb_output_path'
        """
        json_index_outputpath = f"{eventkb_output_path}/indices/{self.file_prefix}_image_tsindex.json"
        frame_outputpath = f"{eventkb_output_path}/data/frames/{self.file_prefix}"
        make_tempdirs(os.path.dirname(json_index_outputpath))
        make_tempdirs(frame_outputpath)
        threshold_ratio = 0.2
        debug_outfile = f"{eventkb_output_path}/debug/{self.file_prefix}_debug_outvideo.mp4"
        make_tempdirs(os.path.dirname(debug_outfile))
        frame_writer = OpenCVFrameWriter(self.video_filepath, json_index_outputpath, frame_outputpath, threshold_ratio)
        frame_writer.process_video(debug_outfile)

    def extract_images(self, images_output_path):
        """
        Convert a video to a sequence of images and save them to the output folder. Currently, blindly does one 
        image per 5 sec (fps at 0.2)
        """
        clip = VideoFileClip(self.video_filepath)
        make_tempdirs(images_output_path)
        print(f"Extracting frames to {images_output_path}")
        clip.write_images_sequence(
            os.path.join(images_output_path, "frame%04d.png"), fps=0.2 #configure this for controlling frame rate.
        )

    def extract_text_with_index(self, eventkb_output_path):
        whisper = WhisperTurbo(model_type=WhisperTurbo.SMALL_MODEL)
        whisper.load()
        self.text_filepath = f"{eventkb_output_path}/transcripts/{self.file_prefix}_transcription_full.txt"
        make_tempdirs(os.path.dirname(self.text_filepath))
        whisper.transcribe(self.video_filepath, self.text_filepath)
        json_index_outputpath = f"{eventkb_output_path}/indices/{self.file_prefix}_text_tsindex.json"
        make_tempdirs(os.path.dirname(json_index_outputpath))
        whisper.output_text_jsonindex(json_index_outputpath)
        text_outpath = f"{eventkb_output_path}/data/shards/{self.file_prefix}"
        make_tempdirs(text_outpath)
        whisper.output_textonly_shards(text_outpath)

    def extract_text(self, text_outfile):
        """
        Extracts text from an audio file using whisper speech recognition (for English only)
        """
        print("Extracting text ..")
        recognizer = sr.Recognizer()
        audio = sr.AudioFile(self.audio_filepath)

        with audio as source:
            # Record the audio data
            audio_data = recognizer.record(source)

            try:
                # Recognize the speech
                text = recognizer.recognize_whisper(audio_data)
                self.text_filepath = text_outfile
                 # Save text to file
                with open(text_outfile, 'w') as file:
                    file.write(text)
            except sr.UnknownValueError:
                print("Speech recognition could not understand the audio.")
            except sr.RequestError as e:
                print(f"Could not request results from service; {e}")

        return text

    def download(self, output_folder=_example_output_folder):
        make_tempdirs(output_folder)
        (_, video_outfile) = self._download_video(output_folder)
        self.video_filepath = f"{output_folder}/{video_outfile}"
        self.file_prefix = Path(self.video_filepath).stem
    
    def process_video_with_index(self, events_folder):
        self.audio_filepath = get_audio_outfile(self.video_filepath)
        self.extract_audio(self.audio_filepath)
        self.extract_text_with_index(events_folder)
        return (self.video_filepath, self.audio_filepath, self.text_filepath)
        

    def process_video_legacy(self):
        """
        Downloads video from the given YouTube URL, extracts audio and text.
        Returns:
            (video filepath, audio filepath, text filepath)
        """
        # Video must have been already downloaded if url was provided.
        self.audio_filepath = get_audio_outfile(self.video_filepath)
        self.text_filepath = get_text_outfile(self.video_filepath)

        self.extract_audio(self.audio_filepath)
        self.extract_text(self.text_filepath)
        
        print(f"Video transcript saved as {self.text_filepath}")
        return (self.video_filepath, self.audio_filepath, self.text_filepath)

def save_uploaded_media(uploaded_media, output_folder=Video._example_output_folder):
    """
    Save uploaded media file (video or audio) to the output folder.
    
    Returns:
        (media filepath)
    """
    make_tempdirs(output_folder)
    rnd_str = generate_random_string(10)
    file_name, file_ext = get_file_parts(uploaded_media)
    media_outfile = generate_filename(f'{file_name}', rnd_str, file_ext)
    print(f"Saving media as {media_outfile}")
    media_path = f"{output_folder}/{media_outfile}"
    with open(media_path, "wb") as f:
        f.write(uploaded_media.getvalue())
    return media_path, file_name, file_ext

def process_uploaded_media(uploaded_media, output_folder=Video._example_output_folder):
    """
    Process uploaded media file (video or audio) and extracts text.
    Returns:
        (media filepath, text filepath)
    """
    media_path, file_name, file_ext = save_uploaded_media(uploaded_media, output_folder)
    if file_ext not in {"mp4", "wav", "mp3", "txt"}:
        return None, None, None
    if file_ext == "mp4":
        video = Video.from_file(media_path)
        return video.process_video_legacy()
    elif file_ext in {"wav", "mp3"}:
        audio_path = media_path
        text_path = get_text_outfile(media_path, file_ext)
        text = extract_text(audio_path, text_path)
        # Save text to file
        with open(text_path, 'w') as file:
            file.write(text)
        return (media_path, audio_path, text_path)
    elif file_ext == "txt":
        text_path = media_path
        return (media_path, media_path, text_path)
    
def run_main():
    parser = argparse.ArgumentParser(description="Process a YouTube video.")

    parser.add_argument('-y', '--youtube_url', type=str, nargs='?',
                        default=Video._example_video_url, help=f"A YouTube url to process, default: {Video._example_video_url}")

    parser.add_argument('-o', '--output_folder', type=str, nargs='?', default=Video._example_output_folder, 
                        help=f"Output folder (default: {Video._example_output_folder})")

    args = parser.parse_args()

    print("YouTube url:", args.youtube_url)
    print("Output folder: ", args.output_folder)
    video = Video.from_url(args.youtube_url)
    video.download(args.output_folder)
    (v, a, t) = video.process_video_legacy()
    video.extract_images("./temp/images/")
    print(f"Video saved as {v}, audio as {a}, text as {t}")

if __name__ == "__main__":
    run_main()