# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.0.1"
  sha256 "2FE7262C98DCA4C0DC98276CAB2FBDDE3C9CC747A621F12F8CB36173E6C100C4"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.0.1/Murmur.AI_1.0.1_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
