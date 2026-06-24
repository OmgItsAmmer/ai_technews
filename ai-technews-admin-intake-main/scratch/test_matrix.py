"""
End-to-end QA test matrix for Admin Add News endpoints.
Runs against the live dev server (http://127.0.0.1:8000).

Scenarios exercised:
  1.  Tech article text  → valid extraction with title + tags
  2.  Non-tech content   → is_valid_news=False
  3.  Text with no clear author/date → missing_fields populated
  4.  Raw JSON payload   → valid extraction
  5.  Raw XML <item>     → valid extraction
  6.  Publish with empty tags → 400 error
  7.  Publish same URL twice  → 409 conflict on second attempt
"""

import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8000"


def login(session: requests.Session) -> str:
    """Login as admin and return the refreshed CSRF token."""
    login_url = f"{BASE_URL}/admin/login/"
    # Seed the CSRF cookie
    res = session.get(login_url)
    res.raise_for_status()
    csrf = session.cookies.get("csrftoken")

    login_res = session.post(
        login_url,
        data={
            "username": "admin",
            "password": "admin",
            "csrfmiddlewaretoken": csrf,
            "next": "/admin/",
        },
        headers={"Referer": login_url},
    )
    if login_res.status_code not in (200, 302):
        print(f"Login HTTP status: {login_res.status_code}")
        sys.exit(1)

    print("✓ Logged in as admin.")
    return session.cookies.get("csrftoken")


def extract(session, headers, mode, content):
    res = session.post(
        f"{BASE_URL}/admin/extract-preview/",
        json={"mode": mode, "content": content},
        headers=headers,
    )
    return res.status_code, res.json()


def publish(session, headers, payload):
    res = session.post(
        f"{BASE_URL}/admin/publish/",
        json=payload,
        headers=headers,
    )
    return res.status_code, res.json()


def run():
    session = requests.Session()
    csrf = login(session)
    hdrs = {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
        "Referer": f"{BASE_URL}/admin/",
    }

    failures = []

    # ── Scenario 1: Valid tech article text ────────────────────────────────────
    print("\n[S1] Tech article text → expect is_valid_news=True + tags present")
    code, data = extract(
        session, hdrs, "text",
        "OpenAI has announced GPT-5, its most capable language model to date. "
        "The model achieves state-of-the-art performance on coding and reasoning benchmarks. "
        "It will be available to API developers starting next week.",
    )
    print(f"  Status {code} | is_valid_news={data.get('is_valid_news')} | tags={data.get('tags')}")
    if code != 200 or not data.get("is_valid_news") or not data.get("tags"):
        failures.append("S1: valid tech article failed")

    # ── Scenario 2: Non-tech content → is_valid_news=False ────────────────────
    print("\n[S2] Recipe content → expect is_valid_news=False")
    code, data = extract(
        session, hdrs, "text",
        "Ingredients: 2 cups of flour, 1 cup of sugar, 1/2 cup of butter. "
        "Mix together and bake at 350°F for 25 minutes. Let cool before serving.",
    )
    print(f"  Status {code} | is_valid_news={data.get('is_valid_news')}")
    if code != 200 or data.get("is_valid_news") is not False:
        failures.append("S2: non-tech content not rejected")

    # ── Scenario 3: Text with no author/date → missing_fields populated ────────
    print("\n[S3] Text missing author/date → expect missing_fields contains them")
    code, data = extract(
        session, hdrs, "text",
        "Apple introduced a new version of Apple Intelligence featuring on-device LLMs "
        "that can draft emails and summarise notifications without internet access.",
    )
    print(f"  Status {code} | missing_fields={data.get('missing_fields')}")
    mf = data.get("missing_fields", [])
    if code != 200 or ("author" not in mf and "published_at" not in mf):
        failures.append("S3: missing fields not correctly detected")

    # ── Scenario 4: Raw JSON payload ──────────────────────────────────────────
    print("\n[S4] Raw JSON text → expect is_valid_news=True")
    code, data = extract(
        session, hdrs, "text",
        json.dumps({
            "headline": "NVIDIA Unveils Blackwell Ultra GPU Architecture",
            "body": (
                "NVIDIA revealed its next-generation Blackwell Ultra GPU at GTC 2026, "
                "promising 4x the performance of Hopper for LLM inference workloads. "
                "Cloud providers will receive allocations in Q3 2026."
            ),
        }),
    )
    print(f"  Status {code} | is_valid_news={data.get('is_valid_news')}")
    if code != 200 or not data.get("is_valid_news"):
        failures.append("S4: raw JSON extraction failed")

    # ── Scenario 5: Raw XML <item> ─────────────────────────────────────────────
    print("\n[S5] Raw XML <item> → expect is_valid_news=True")
    code, data = extract(
        session, hdrs, "text",
        "<item>"
        "<title>Major Cybersecurity Breach Exposes 50 M Records</title>"
        "<description>"
        "A critical zero-day vulnerability in a popular cloud database provider "
        "was exploited, exposing sensitive customer data from 50 million accounts. "
        "Researchers have labelled it one of the worst data breaches of the year."
        "</description>"
        "</item>",
    )
    print(f"  Status {code} | is_valid_news={data.get('is_valid_news')}")
    if code != 200 or not data.get("is_valid_news"):
        failures.append("S5: raw XML extraction failed")

    # ── Scenario 6: Publish with empty tags → 400 ─────────────────────────────
    print("\n[S6] Publish with empty tags → expect HTTP 400")
    code, data = publish(
        session, hdrs,
        {
            "title": "No-Tags Article",
            "author": "Jane Doe",
            "published_at": "2026-06-24T12:00:00Z",
            "summary": "An interesting AI article.",
            "tags": [],
            "original_url": "https://example.com/no-tags-article",
            "raw_input": "Full article body.",
        },
    )
    print(f"  Status {code} | detail={data.get('detail')}")
    if code != 400 or data.get("status") != "error":
        failures.append("S6: empty-tags should have been rejected with 400")

    # ── Scenario 7: Duplicate URL → 409 on second attempt ────────────────────
    print("\n[S7] Publish same URL twice → expect 201 then 409")
    url = "https://example.com/duplicate-url-scenario-7"
    pub_payload = {
        "title": "Unique Article Title",
        "author": "Jane Doe",
        "published_at": "2026-06-24T12:00:00Z",
        "summary": "A great summary.",
        "tags": ["llms"],
        "original_url": url,
        "raw_input": "Full article body.",
    }
    code1, data1 = publish(session, hdrs, pub_payload)
    code2, data2 = publish(session, hdrs, pub_payload)
    print(f"  First publish:  {code1} | status={data1.get('status')}")
    print(f"  Second publish: {code2} | status={data2.get('status')} | detail={data2.get('detail')}")
    if code1 != 201:
        failures.append(f"S7: first publish should be 201, got {code1}")
    if code2 != 409 or data2.get("status") != "error":
        failures.append(f"S7: second publish should be 409, got {code2}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    else:
        print("ALL 7 SCENARIOS PASSED ✓")


if __name__ == "__main__":
    run()
