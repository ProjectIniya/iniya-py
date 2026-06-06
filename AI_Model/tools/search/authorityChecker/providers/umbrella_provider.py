import csv
import math
import zipfile
import requests
import time

from pathlib import Path
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_exponential


from AI_Model.tools.search.authorityChecker.providers.base import AuthorityProvider, SignalResult

MAX_AGE = 60 * 60 * 24 * 7


UMB_DOMAIN_URL = (
    "http://s3-us-west-1.amazonaws.com/"
    "umbrella-static/top-1m.csv.zip"
)

UMB_TLD_URL = (
    "http://s3-us-west-1.amazonaws.com/"
    "umbrella-static/top-1m-TLD.csv.zip"
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "cache" / "umbrella"

DOMAIN_ZIP = DATA_DIR / "top-1m.csv.zip"
DOMAIN_CSV = DATA_DIR / "top-1m.csv"

TLD_ZIP = DATA_DIR / "top-1m-TLD.csv.zip"
TLD_CSV = DATA_DIR / "top-1m-TLD.csv"

def is_stale(path):
    if not path.exists():
        return True

    age = time.time() - path.stat().st_mtime

    return age > MAX_AGE


class UmbrellaProvider(AuthorityProvider):
    name = "umbrella"
    weight = 0.25

    def __init__(self):
        self.domain_ranks = {}
        self.tld_ranks = {}

        self.ensure_dataset()
        self.load_dataset()


    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential()
    )
    def download_and_extract(
        self,
        url,
        zip_path,
        extract_dir
    ):
        response = requests.get(
            url,
            stream=True,
            timeout=30
        )

        response.raise_for_status()
        
        tmp_path = zip_path.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        tmp_path.rename(zip_path)
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)

        except zipfile.BadZipFile:
            zip_path.unlink(missing_ok=True)

            raise Exception(
                "Downloaded ZIP corrupted"
            )

        zip_path.unlink(missing_ok=True)

    def ensure_dataset(self):
        DATA_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        if is_stale(DOMAIN_CSV):
            print(
                "[Umbrella] Downloading "
                "domain rankings..."
            )

            self.download_and_extract(
                UMB_DOMAIN_URL,
                DOMAIN_ZIP,
                DATA_DIR
            )

        if not TLD_CSV.exists():
            print(
                "[Umbrella] Downloading "
                "TLD rankings..."
            )

            self.download_and_extract(
                UMB_TLD_URL,
                TLD_ZIP,
                DATA_DIR
            )

    def normalize(self, rank):
        try:
            rank = int(rank)

            if rank <= 0:
                return 0.0

            score = 1 / (
                1 + math.log10(rank)
            )

            return max(
                0.0,
                min(score, 1.0)
            )

        except:
            return 0.0

    def load_dataset(self):
        print(
            "[Umbrella] Loading "
            "domain rankings..."
        )

        with open(
            DOMAIN_CSV,
            encoding="utf-8"
        ) as f:

            reader = csv.reader(f)

            for row in reader:
                try:
                    rank, domain = row

                    self.domain_ranks[
                        domain
                    ] = int(rank)

                except:
                    continue

        print(
            "[Umbrella] Loading "
            "TLD rankings..."
        )

        with open(
            TLD_CSV,
            encoding="utf-8"
        ) as f:

            reader = csv.reader(f)

            for row in reader:
                try:
                    rank, tld = row

                    self.tld_ranks[
                        tld.lower()
                    ] = int(rank)

                except:
                    continue

        print(
            f"[Umbrella] Loaded "
            f"{len(self.domain_ranks):,} "
            f"domains and "
            f"{len(self.tld_ranks):,} "
            f"TLDs"
        )

    def get_tld_score(self, domain):
        try:
            tld = domain.split(".")[-1].lower()

            rank = self.tld_ranks.get(tld)

            return self.normalize(rank)

        except:
            return 0.0

    async def evaluate(self, domain, _):
        try:
            domain_rank = self.domain_ranks.get(
                domain
            )

            domain_score = self.normalize(
                domain_rank
            )

            tld_score = self.get_tld_score(
                domain
            )

            final_score = (
                domain_score * 0.85 +
                tld_score * 0.15
            )

            return SignalResult(
                provider=self.name,
                score=round(final_score, 4),
                confidence=0.9,
                metadata={
                    "domain_rank": domain_rank,
                    "domain_score": round(
                        domain_score,
                        4
                    ),
                    "tld_score": round(
                        tld_score,
                        4
                    ),
                    "tld": domain.split(".")[-1]
                }
            )

        except Exception as e:
            return SignalResult(
                provider=self.name,
                score=0.0,
                confidence=0.0,
                metadata={
                    "error": str(e)
                }
            )