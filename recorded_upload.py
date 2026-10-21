import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(storage_state="hudl_auth.json")
    page = context.new_page()
    page.goto("https://www.hudl.com/home")
    page.get_by_role("link", name="Upload Upload").click()
    page.get_by_role("button", name="uidismiss").click()
    page.get_by_role("button", name="Select Files").click()
    page.locator("input[type=\"file\"]").first.set_input_files(["clip_007.mp4", "clip_008.mp4"])
    page.get_by_role("button", name="Upload").click()
    page.locator("span").filter(has_text=re.compile(r"^uiexpandregionvertical$")).click()
    page.get_by_role("option", name="Preseason January 10,").click()
    page.get_by_role("textbox", name="Playlist Name").click()
    page.get_by_role("textbox", name="Playlist Name").fill("21-10-2026-Session1")
    page.get_by_role("button", name="Save").click()
    page.goto("https://app.hudl.com/watch/team/117692/analyze?l=liim0-flfl0&ref=primaryNav")
    page.get_by_role("button", name="View Grid").click()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
