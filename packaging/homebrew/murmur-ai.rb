# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.52"
  sha256 "D46934AC103C45A8543F6C3912B7EB152109774A20FDE9E83D5376697D835EDE"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.52/Murmur.AI_1.2.52_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
