# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.36"
  sha256 "9AC3875463C5AC6C9DD1F72D7EE9A81B225C69E6F597037EFA1122D9CB4A1697"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.36/Murmur.AI_1.2.36_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
