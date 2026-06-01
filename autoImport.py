import os
import requests
import unicodedata
import time

# CONFIGURATION — set via environment variables or edit here
KOMGA_URL = os.getenv("KOMGA_URL", "http://localhost:25600")
API_LIBRARIES_ENDPOINT = f"{KOMGA_URL}/api/v1/libraries"
KOMGA_USERNAME = os.getenv("KOMGA_USERNAME", "")
KOMGA_PASSWORD = os.getenv("KOMGA_PASSWORD", "")

BOOKS_ROOT_HOST = os.getenv("BOOKS_ROOT_HOST", "/books")  # Host path
BOOKS_ROOT_DOCKER = os.getenv("KOMGA_BOOKS_ROOT_DOCKER", "/books")  # Path as seen by Komga Docker

# AUTH
session = requests.Session()
session.auth = (KOMGA_USERNAME, KOMGA_PASSWORD)

# Sanitize names for Komga library display
def sanitize_name(name):
    return unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()

# Get existing libraries
response = session.get(API_LIBRARIES_ENDPOINT)
response.raise_for_status()
existing_libraries = {lib["root"]: lib for lib in response.json()}

# Process folders
for folder_name in os.listdir(BOOKS_ROOT_HOST):
    full_host_path = os.path.join(BOOKS_ROOT_HOST, folder_name)
    full_docker_path = os.path.join(BOOKS_ROOT_DOCKER, folder_name)

    if not os.path.isdir(full_host_path):
        continue

    library_name = sanitize_name(folder_name)

    if full_docker_path in existing_libraries:
        print(f"Library '{existing_libraries[full_docker_path]['name']}' already exists, skipping.")
        continue

    print(f"Creating library for '{library_name}'...")

    payload = {
        "name": library_name,
        "root": full_docker_path,
        "importComicInfoBook": True,
        "importComicInfoSeries": True,
        "importComicInfoCollection": True,
        "importEpubBook": True,
        "importEpubSeries": True,
        "scanForceModifiedTime": True,
        "repairExtensions": True,
        "convertToCbz": True,
        "emptyTrashAfterScan": True,
        "scanOnStartup": True
    }

    create_resp = session.post(API_LIBRARIES_ENDPOINT, json=payload)

    if not create_resp.ok:
        print(f"❌ Failed to create library '{library_name}': {create_resp.status_code} - {create_resp.text}")
        continue

    print(f"✅ Library '{library_name}' created.")

    # Wait to prevent race condition with automatic scan
    time.sleep(2)

    # Trigger shallow scan
    new_library_id = create_resp.json().get("id")
    scan_url = f"{API_LIBRARIES_ENDPOINT}/{new_library_id}/scan?deep=false"
    scan_resp = session.post(scan_url)

    if scan_resp.ok:
        print(f"📚 Triggered shallow scan for '{library_name}'")
    else:
        print(f"⚠️ Failed to trigger shallow scan for '{library_name}': {scan_resp.status_code} - {scan_resp.text}")

print("🎉 Done syncing and scanning libraries.")
