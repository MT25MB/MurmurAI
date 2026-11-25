# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.40"
  sha256 "B39F0E372DE05121405E0236504936A7EFB76BFBD568393E413BE35235953571"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.40/Murmur.AI_1.2.40_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
