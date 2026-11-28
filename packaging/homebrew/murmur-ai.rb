# Homebrew Cask template for Murmur AI (Apple Silicon).
# Placeholders are filled by scripts/sync_packaging.py on every release.
cask "murmur-ai" do
  version "1.2.73"
  sha256 "94106D7E9F678030173758D3AC4C32300E709289EB75D3AD76EFA7476DAC7E5F"

  url "https://github.com/MT25MB/MurmurAI/releases/download/v1.2.73/Murmur.AI_1.2.73_aarch64.dmg"
  name "Murmur AI"
  desc "100% local voice-controlled desktop agent"
  homepage "https://MT25MB.github.io/MurmurAI/"

  app "Murmur AI.app"
  # No zap: user data and local model weights must survive uninstall unless
  # the user explicitly opts in via clear_data_on_uninstall.
end
