# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.12"
  sha256 "88B5DB4A69084C78CCF7D99021C384E440CCA7C71CF35B89C118367D548F1E88"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.12/Murmur.AI_1.2.12_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
