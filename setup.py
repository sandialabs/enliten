# setup.py
from setuptools import setup, find_packages
setup(
    name="enliten",
    version="0.2.0",
    packages=find_packages(),
    install_requires=["numpy>=1.26", "numpy-financial>=1.0", "pandas>=2.2", "matplotlib>=3.8"],
    extras_require={"notebooks": ["jupyter>=1.0"]},
)
