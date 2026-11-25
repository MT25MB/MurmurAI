# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.26"
  sha256 "C4F275CE9BFCA181234DA73F661379FD3E9FEF523EC40CDDA0B88D0B3BB69D76"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.26/Murmur.AI_1.2.26_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
