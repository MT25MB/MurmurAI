# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.42"
  sha256 "B2E96E67A8D551F2EB1A62F5F03EC4D5411B6C485EEEE49F04F1A88E84BCA006"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.42/Murmur.AI_1.2.42_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
