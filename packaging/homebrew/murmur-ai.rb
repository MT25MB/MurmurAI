# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.55"
  sha256 "3C56FED58C8AB102C593B1B7A279B82B4127A663B93A5ADAAC2DCECBB682DBF6"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.55/Murmur.AI_1.2.55_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
