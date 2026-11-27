# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.57"
  sha256 "52FC3D35FEAE051E76C7A38E4483A308BEC0A63D428AC2E030EB01A85A2F3F24"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.57/Murmur.AI_1.2.57_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
