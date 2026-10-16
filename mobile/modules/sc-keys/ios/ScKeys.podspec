Pod::Spec.new do |s|
  s.name           = 'ScKeys'
  s.version        = '0.1.0'
  s.summary        = 'Secure Enclave P-256 keys for StormCash'
  s.author         = 'StormCash'
  s.homepage       = 'https://github.com/Alexlgvcode/stormcash'
  s.license        = 'MIT'
  s.platforms      = { :ios => '15.1' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.source_files = '**/*.swift'
end
