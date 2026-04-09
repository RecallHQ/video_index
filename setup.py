import os
from setuptools import setup, find_packages
 
# Read requirements without pkg_resources
def read_requirements():
    with open(os.path.join(os.path.dirname(__file__), "requirements.txt")) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]
 
setup(
    install_requires=read_requirements(),
)
