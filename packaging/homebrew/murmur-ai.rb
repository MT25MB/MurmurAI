# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.6"
  sha256 "C62AE11AE17085923B235791B403FEF5DB1E4E8932C14E18447132BEB1DE6C7F"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.6/Murmur.AI_1.2.6_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
