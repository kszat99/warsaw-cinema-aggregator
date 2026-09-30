"""Scoped B2 metadata checks; secrets and response bodies never enter logs."""

import re
from typing import Any

import httpx

PREFIX = "cinema-pilot-v1/"


class B2:
    def __init__(self, client: httpx.Client, config: dict[str, str]) -> None:
        self.client = client
        bucket = config["bucket_name"]
        if not re.fullmatch(r"[A-Za-z0-9-]{6,63}", bucket):
            raise ValueError("Invalid bucket")
        response = client.get(
            "https://api.backblazeb2.com/b2api/v4/b2_authorize_account",
            auth=(config["application_key_id"], config["application_key"]),
            follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        api = data["apiInfo"]["storageApi"]
        allowed = api["allowed"]
        buckets = allowed.get("buckets") or []
        if len(buckets) != 1 or buckets[0].get("name") != bucket:
            raise ValueError("Key must match one bucket")
        if allowed.get("namePrefix") not in (None, "", PREFIX):
            raise ValueError("Unexpected key prefix")
        self.bucket_id = buckets[0]["id"]
        self.account_id = data["accountId"]
        self.token = data["authorizationToken"]
        self.api = api["apiUrl"]
        self.s3 = api["s3ApiUrl"]
        if not re.fullmatch(r"https://api[0-9]+\.backblazeb2\.com", self.api):
            raise ValueError("Unexpected API origin")
        if not re.fullmatch(r"https://s3\.[a-z0-9-]+\.backblazeb2\.com", self.s3):
            raise ValueError("Unexpected S3 origin")
        required = {"listFiles", "readFiles", "writeFiles", "deleteFiles"}
        if not required.issubset(allowed["capabilities"]):
            raise ValueError("Missing backup permissions")
        self.repository = f"s3:{self.s3}/{bucket}/{PREFIX.rstrip('/')}"

    def call(self, method: str, values: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            self.api + "/b2api/v4/" + method,
            headers={"Authorization": self.token},
            json=values,
            follow_redirects=False,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def bucket(self) -> dict[str, Any]:
        rows = self.call(
            "b2_list_buckets",
            {
                "accountId": self.account_id,
                "bucketId": self.bucket_id,
            },
        )["buckets"]
        if len(rows) != 1 or rows[0]["bucketId"] != self.bucket_id:
            raise ValueError("Unexpected bucket response")
        if rows[0]["bucketType"] != "allPrivate":
            raise ValueError("Backup bucket is not private")
        result: dict[str, Any] = rows[0]
        return result

    def check_lifecycle(self, *, configure: bool = False) -> None:
        bucket = self.bucket()
        rules = bucket.get("lifecycleRules", [])
        desired = {
            "fileNamePrefix": PREFIX,
            "daysFromHidingToDeleting": 1,
            "daysFromUploadingToHiding": None,
        }
        overlapping = [
            r
            for r in rules
            if PREFIX.startswith(r["fileNamePrefix"])
            or r["fileNamePrefix"].startswith(PREFIX)
        ]
        if len(overlapping) == 1 and all(
            overlapping[0].get(k) == v for k, v in desired.items()
        ):
            return
        if overlapping or not configure:
            raise ValueError("Backup lifecycle requires review")
        # Only our repository prefix; preserve all other bucket lifecycle settings.
        self.call(
            "b2_update_bucket",
            {
                "accountId": self.account_id,
                "bucketId": self.bucket_id,
                "ifRevisionIs": bucket["revision"],
                "lifecycleRules": [*rules, desired],
            },
        )
        self.check_lifecycle()

    def stored_bytes(self) -> int:
        values: dict[str, Any] = {"bucketId": self.bucket_id, "maxFileCount": 1000}
        total = 0
        # Include hidden versions, unlike S3 listings. Bound work on malformed listings.
        for _ in range(100):
            page = self.call("b2_list_file_versions", values)
            for item in page["files"]:
                size = item["contentLength"]
                if type(size) is not int or size < 0:
                    raise ValueError("Invalid stored size")
                total += size
            if not page.get("nextFileName"):
                return total
            values.update(
                startFileName=page["nextFileName"], startFileId=page["nextFileId"]
            )
        raise ValueError("Bucket listing limit reached")
