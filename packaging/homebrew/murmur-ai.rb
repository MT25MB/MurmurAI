# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.78"
  sha256 "F5A7298DF48A42CF2C91DDED2047F9672CE396227E32D27A7077F622341F99FB"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.78/Murmur.AI_1.2.78_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
