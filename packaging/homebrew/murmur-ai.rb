# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.72"
  sha256 "2B7D74B7A8A5B44FE4D2A74A2C54D6D9C92BAB1DF88D37A2B928463CAA0DDE08"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.72/Murmur.AI_1.2.72_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
