// Single source of truth for the GitHub repo used by the download button and
// all "view source" links. Change these two values to re-point the whole site.
export const REPO_OWNER = "MT25MB";
export const REPO_NAME = "MurmurAI";

export const REPO_SLUG = `${REPO_OWNER}/${REPO_NAME}`;
export const REPO_URL = `https://github.com/${REPO_SLUG}`;
export const RELEASES_URL = `${REPO_URL}/releases`;
export const LATEST_RELEASE_API = `https://api.github.com/repos/${REPO_SLUG}/releases/latest`;
