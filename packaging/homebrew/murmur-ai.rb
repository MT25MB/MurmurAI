# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.2"
  sha256 "BFA6640AE78F62DE8B378DA19F58F2BB8402592751C962C84DB3408452749A90"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.2/Murmur.AI_1.2.2_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
