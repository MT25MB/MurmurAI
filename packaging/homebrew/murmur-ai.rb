# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.7"
  sha256 "C6CFD17C2589200A80E1A0BED8BAD43C5AB2ED7B33507D6147ED5B7C8C1A27D9"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.7/Murmur.AI_1.2.7_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
