# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.63"
  sha256 "4001271936D0DDDC73395835BCDF03F65DFC46300665E3DC27D8872048D932BF"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.63/Murmur.AI_1.2.63_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
