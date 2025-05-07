import os


def main():
    """Interactive configuration to set API keys for various services."""
    config_path = os.path.expanduser("~/.fulltext_keys")
    existing = {}
    if os.path.exists(config_path):
        # Load existing keys
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    existing[key.strip()] = val.strip()
        except Exception as e:
            print(f"Warning: unable to read existing config file: {e}")
    print("Configuring API keys for fulltext-article-downloader.")
    print(
        "Press Enter without typing to keep an existing value or skip setting a new one.")
    keys = {}
    # List of keys to configure and prompts
    key_prompts = [
        ("ELSEVIER_API_KEY", "Elsevier API Key"),
        ("SPRINGER_API_KEY", "Springer API Key"),
        ("WILEY_API_KEY", "Wiley API Key"),
        ("UNPAYWALL_EMAIL", "Unpaywall contact email")
    ]
    for key, description in key_prompts:
        if key in existing and existing[key]:
            user_input = input(f"{description} (leave blank to keep current): ")
            if user_input.strip() == "":
                # Keep existing
                keys[key] = existing[key]
            else:
                keys[key] = user_input.strip()
        else:
            user_input = input(f"{description}: ")
            if user_input.strip() != "":
                keys[key] = user_input.strip()
    # Write out the keys to config file
    try:
        with open(config_path, 'w') as f:
            for k, v in keys.items():
                f.write(f"{k}={v}\n")
        print(f"Configuration saved to {config_path}")
    except Exception as e:
        print(f"Error: Could not write configuration file: {e}")
        return
