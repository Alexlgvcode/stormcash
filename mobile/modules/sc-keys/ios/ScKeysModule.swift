import ExpoModulesCore
import Foundation
import Security

// Secure Enclave P-256 signing key (spec §19.6). The private key never leaves the enclave.
public class ScKeysModule: Module {
  public func definition() -> ModuleDefinition {
    Name("ScKeys")

    Function("isAvailable") { () -> Bool in
      #if targetEnvironment(simulator)
        return false
      #else
        return true
      #endif
    }

    Function("getOrCreatePublicKey") { (tag: String) throws -> String in
      let key = try Self.findKey(tag) ?? Self.createKey(tag)
      guard let pub = SecKeyCopyPublicKey(key),
            let data = SecKeyCopyExternalRepresentation(pub, nil) as Data? else {
        throw Exception(name: "PublicKey", description: "Could not export the public key")
      }
      return data.hex
    }

    Function("signDigest") { (tag: String, digestHex: String) throws -> String in
      guard let key = try Self.findKey(tag) else {
        throw Exception(name: "NoKey", description: "No Secure Enclave key for \(tag)")
      }
      guard let digest = Data(hex: digestHex), digest.count == 32 else {
        throw Exception(name: "BadDigest", description: "Digest must be 32 bytes of hex")
      }
      var error: Unmanaged<CFError>?
      guard let sig = SecKeyCreateSignature(
        key, .ecdsaSignatureDigestX962SHA256, digest as CFData, &error) as Data? else {
        throw Exception(name: "Sign", description: error?.takeRetainedValue().localizedDescription ?? "sign failed")
      }
      return sig.hex
    }

    Function("deleteKey") { (tag: String) in
      SecItemDelete([
        kSecClass: kSecClassKey,
        kSecAttrApplicationTag: Data(tag.utf8),
      ] as CFDictionary)
    }
  }

  private static func findKey(_ tag: String) throws -> SecKey? {
    var item: CFTypeRef?
    let status = SecItemCopyMatching([
      kSecClass: kSecClassKey,
      kSecAttrApplicationTag: Data(tag.utf8),
      kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
      kSecReturnRef: true,
    ] as CFDictionary, &item)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let found = item else {
      throw Exception(name: "Keychain", description: "SecItemCopyMatching failed: \(status)")
    }
    return (found as! SecKey)
  }

  private static func createKey(_ tag: String) throws -> SecKey {
    guard let access = SecAccessControlCreateWithFlags(
      nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .privateKeyUsage, nil) else {
      throw Exception(name: "Access", description: "Could not create access control")
    }
    var error: Unmanaged<CFError>?
    guard let key = SecKeyCreateRandomKey([
      kSecAttrKeyType: kSecAttrKeyTypeECSECPrimeRandom,
      kSecAttrKeySizeInBits: 256,
      kSecAttrTokenID: kSecAttrTokenIDSecureEnclave,
      kSecPrivateKeyAttrs: [
        kSecAttrIsPermanent: true,
        kSecAttrApplicationTag: Data(tag.utf8),
        kSecAttrAccessControl: access,
      ],
    ] as CFDictionary, &error) else {
      throw Exception(name: "Create", description: error?.takeRetainedValue().localizedDescription ?? "create failed")
    }
    return key
  }
}

private extension Data {
  var hex: String { map { String(format: "%02x", $0) }.joined() }

  init?(hex: String) {
    guard hex.count % 2 == 0 else { return nil }
    var bytes = [UInt8]()
    var i = hex.startIndex
    while i < hex.endIndex {
      let j = hex.index(i, offsetBy: 2)
      guard let b = UInt8(hex[i..<j], radix: 16) else { return nil }
      bytes.append(b)
      i = j
    }
    self.init(bytes)
  }
}
