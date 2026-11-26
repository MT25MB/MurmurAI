# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.49"
  sha256 "C0E5B34DE13900174DE40348C1B4FFB3B3536060EF9B129BB8DE6B608614FA97"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.49/Murmur.AI_1.2.49_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
