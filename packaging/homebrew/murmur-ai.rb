# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.28"
  sha256 "317402764D31B648D03907DC48BD46D608808988171DB50C25B0EBBCB99760CC"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.28/Murmur.AI_1.2.28_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
