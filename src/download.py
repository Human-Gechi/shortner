import os
import tarfile
import urllib.request

LICENSE_KEY = os.getenv("MAXMIND_LICENSE_KEY")
EDITION_ID = "GeoLite2-City"

if not LICENSE_KEY:
    print("Skipping GeoIP download: MAXMIND_LICENSE_KEY is not set.")
    exit(0)

url = f"https://download.maxmind.com/app/geoip_download?edition_id={EDITION_ID}&license_key={LICENSE_KEY}&suffix=tar.gz"
output_archive = "geoip.tar.gz"
target_dir = "GeoLite2-City"

print("Downloading GeoLite2 City database...")
urllib.request.urlretrieve(url, output_archive)

print("Extracting database file...")
with tarfile.open(output_archive, "r:gz") as tar:
    for member in tar.getmembers():
 
        if member.name.endswith(".mmdb"):

            member.name = os.path.basename(member.name)
            tar.extract(member, path=target_dir)
            print(f"Successfully saved database to {target_dir}/{member.name}")
            
if os.path.exists(output_archive):
    os.remove(output_archive)