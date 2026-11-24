# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.17"
  sha256 "13085E14B1AF041AE662CFCCB6F5D72D807ECBF04B0184C5B40355E885BD303E"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.17/Murmur.AI_1.2.17_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
