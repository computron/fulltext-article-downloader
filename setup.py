import io
import os
from setuptools import setup, find_packages

# Read the README for long description
current_dir = os.path.abspath(os.path.dirname(__file__))
long_description = ""
readme_path = os.path.join(current_dir, "README.md")
if os.path.isfile(readme_path):
    with io.open(readme_path, encoding="utf-8") as f:
        long_description = f.read()

setup(
    name="fulltext-article-downloader",
    version="0.1.0",
    author="Author Name",
    author_email="author@example.com",
    description="A tool to download full-text research articles by DOI using multiple methods (APIs, Open Access, scraping).",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/fulltext-article-downloader",
    license="BSD-3-Clause",
    packages=find_packages(),
    install_requires=[
        "requests>=2.20.0",
        "tqdm>=4.50.0",
        "beautifulsoup4>=4.6.0",
        "browser-cookie3>=0.15.0",
        "sprynger>=0.3.0",
        "paperscraper>=0.1.0"
    ],
    entry_points={
        "console_scripts": [
            "fulltext-download = fulltext_article_downloader.cli:main",
            "fulltext-config = fulltext_article_downloader.configure:main"
        ]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: BSD License",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Information Analysis"
    ],
    python_requires=">=3.6"
)
