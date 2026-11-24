# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.13"
  sha256 "AC7277E179A557593BCA619D72DD548B315CE5F3000B33EA0AE7C3C89F61A750"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.13/Murmur.AI_1.2.13_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
