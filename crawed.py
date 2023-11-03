import requests
import re
import random
from bs4 import BeautifulSoup

r1 = requests.get("https://gelbooru.com/index.php?page=post&s=list&tags=mikeneko_%28utaite%29+")
soup = BeautifulSoup(r1.text, "html.parser")
sel = soup.select("div.pagination a")
regex = re.compile('pid=\d*')
pid = regex.findall(str(sel[-1]))

pid2 = re.search(r"\d+\.?\d*", str(pid)).group(0)
cho = random.randint(0, int(pid2))

r2 = requests.get(f"https://gelbooru.com/index.php?page=post&s=list&tags=mikeneko_%28utaite%29&pid={cho}")
s2 = BeautifulSoup(r2.text, "html.parser")
s3 = s2.select("div.thumbnail-container img")

print(str(s3[0]["src"]).replace("thumbnails", "images").replace("thumbnail_", ""))
