# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.54"
  sha256 "6904E9A5B05A5F2C93811747003A373B7949D542D8B6649D23CD2AA7B01A6D14"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.54/Murmur.AI_1.2.54_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
