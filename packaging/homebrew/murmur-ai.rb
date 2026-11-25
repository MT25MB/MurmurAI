# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.25"
  sha256 "B4045BF3949E209FAF6A56CD5BA053C1EAE5E080441C49A4EF70DDE35B4BA982"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.25/Murmur.AI_1.2.25_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"

  zap trash: [
    "~/.murmur-ai",
  ]
end
