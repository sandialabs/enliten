# setup.py
from setuptools import setup, find_packages
setup(
    name="enliten",
    version="0.2.0",
    packages=find_packages(),
    install_requires=["pandas>=2.2"],
)
