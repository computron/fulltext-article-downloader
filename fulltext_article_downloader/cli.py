import sys
import argparse
from fulltext_article_downloader import download_article


def main():
    parser = argparse.ArgumentParser(prog="fulltext-download",
                                     description="Download the full text of an article by DOI.")
    parser.add_argument("doi", help="DOI of the article to download")
    parser.add_argument("output_dir",
                        help="Directory to save the downloaded file")
    parser.add_argument("output_filename", nargs="?",
                        help="Optional name for the output file (including extension). If not provided, a name based on the DOI will be used.")
    args = parser.parse_args()

    doi = args.doi
    out_dir = args.output_dir
    filename = args.output_filename

    try:
        output_path = download_article(doi, output_dir=out_dir,
                                       output_filename=filename)
        print(f"Successfully downloaded {doi} to {output_path}")
        sys.exit(0)
    except Exception as e:
        print(f"Error downloading {doi}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
