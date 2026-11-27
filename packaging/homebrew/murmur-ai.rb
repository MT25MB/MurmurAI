# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.58"
  sha256 "A891749F7594D394052B68B897F0102D5DBAF44CA8C2F9E145B7F08D26BA7F4B"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.58/Murmur.AI_1.2.58_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
