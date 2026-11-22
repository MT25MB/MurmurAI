# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.0.0"
  sha256 "4C3D806510C483605E6142AE8880B677BDD1C3050692F42395CCC783C9EC4253"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.0.0/Murmur.AI_1.0.0_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
