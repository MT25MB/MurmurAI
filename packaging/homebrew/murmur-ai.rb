# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.8"
  sha256 "00474EA6A3E3B699F5A64CD3E6E86941F5EA82D54223C405388F9B0C5BE4A41D"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.8/Murmur.AI_1.2.8_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
