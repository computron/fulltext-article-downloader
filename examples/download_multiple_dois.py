"""
Example script: Download multiple articles by DOI to a specified directory.
"""
from fulltext_article_downloader import bulk_download_articles

# List of DOIs to download
doi_list = [
    "10.48550/arXiv.2504.00812",       # arXiv (preprint)
    "10.1101/2025.01.06.631505",       # bioRxiv (preprint)
    "10.26434/chemrxiv-2024-x6spt",    # chemRxiv (preprint)
    "10.1002/advs.201900808",          # Wiley
    "10.1371/journal.pone.0171501",    # PLOS ONE (Open Access)
    "10.1186/s41313-024-00053-x",      # Springer / Nature (Open Access)
    "10.1016/j.msea.2025.148402",      # Elsevier
    "10.7554/eLife.12345",             # eLife Sciences (Open Access)
    "10.1017/S0885715624000484",       # Cambridge University Press
    "10.1103/PhysRevLett.114.105503",  # APS (American Physical Society)
]

"""
Note - these are examples of DOIs that will fail due to lack of TDM service and open-access version!
doi_list_failures = [
    "10.1109/GROUP4.2007.4347715",     # IEEE
    "10.1021/acs.chemrev.2c00799",     # ACS (American Chemical Society)
    "10.1063/5.0058579",               # AIP (American Institute of Physics)
    "10.1093/oxfmat/itac006",          # Oxford University Press
    "10.1039/D4DD00074A",              # RSC (Royal Society of Chemistry)
    "10.1126/sciadv.1600225",          # AAAS / Science
    "10.3389/fmats.2025.1600681",      # Frontiers in Materials
    "10.1080/14686996.2023.2261833",   # Taylor & Francis / Informa
]
"""

# Output directory for downloaded files
output_directory = "papers"

# Download all DOIs, with a 0.2-second pause between each to avoid hammering servers.
results = bulk_download_articles(
    doi_list,
    output_dir=output_directory,
    log_file="download.log",
    sleep=0.2,
)

# Print a summary of the results
for doi, result in results.items():
    if isinstance(result, str) and result.startswith("ERROR"):
        print(f"{doi} - Failed to download ({result})")
    else:
        print(f"{doi} - Successfully downloaded to {result}")
