import httpx

def check_cinemas():
    urls = {
        'Amondo': 'https://kinoamondo.pl/repertuar/',
        'Ujazdowski': 'https://u-jazdowski.pl/kino/repertuar'
    }
    with httpx.Client(follow_redirects=True, verify=False) as client:
        for name, url in urls.items():
            try:
                r = client.get(url)
                body = r.text.lower()
                print(f"{name}:")
                if "bilety24" in body:
                    print("- Uses Bilety24")
                    # Try to find the bilety24 URL
                    import re
                    b24 = re.findall(r'https?://[a-zA-Z0-9_\-]+\.bilety24\.pl', body)
                    if b24:
                        print(f"  Bilety24 domain: {list(set(b24))}")
                else:
                    print("- No Bilety24 found")
                    # print some snippet
                    print(body[:200])
            except Exception as e:
                print(f"{name} Error: {e}")

if __name__ == '__main__':
    check_cinemas()
