# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.41"
  sha256 "F9178A63EDDC7AC2A97257C6BBE4A2B4A533F85F5E9CD857BBAE22BD7CAB454B"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.41/Murmur.AI_1.2.41_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
