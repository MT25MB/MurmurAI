# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.46"
  sha256 "49043D2619FBA699F92A0F6B9539259065BF7E7B0FD838EE012075C7A25CCE4A"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.46/Murmur.AI_1.2.46_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
