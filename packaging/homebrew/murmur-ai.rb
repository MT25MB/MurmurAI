# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.51"
  sha256 "C82C6CE49B3CC89D9332412B5EBF10DC9B548AB18F7531AA999D08A51A813A3C"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.51/Murmur.AI_1.2.51_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
