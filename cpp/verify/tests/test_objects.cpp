#include <gtest/gtest.h>

#include "stormcash/crypto.hpp"
#include "support.hpp"

namespace stormcash {
namespace {

Json transport(const std::string& name) { return test::vector("objects", name).at("json"); }

TEST(Codec, TransportRoundTrip) {
  const Json& v = test::vector("objects", "cert_v1");
  Object o = Object::from_json("CERT", v.at("json"));
  EXPECT_EQ(o.canonical(), test::str(v.at("canonical")));
  EXPECT_EQ(o.to_json(), v.at("json"));
  EXPECT_TRUE(o.verify(test::vector_pub("server")));
  EXPECT_EQ(Object::from_fields("CERT", v.at("fields"), v.at("sig")), o);
}

TEST(Codec, RejectsUnknownAndMissingKeys) {
  Json extra = transport("cert_v1");
  extra["note"] = "hi";
  EXPECT_THROW(Object::from_json("CERT", extra), EncodingError);
  Json missing = transport("cert_v1");
  missing.erase("cap");
  EXPECT_THROW(Object::from_json("CERT", missing), EncodingError);
  // Long names are the vector form, not the transport form.
  EXPECT_THROW(Object::from_json("CERT", test::vector("objects", "cert_v1").at("fields")), EncodingError);
}

TEST(Codec, RejectsBadValues) {
  Json padded = transport("cert_v1");
  padded["ci"] = padded["ci"].get<std::string>() + "==";
  EXPECT_THROW(Object::from_json("CERT", padded), EncodingError);

  Json short_id = transport("cert_v1");
  short_id["ci"] = b64u_encode(Bytes(15, 0x01));
  EXPECT_THROW(Object::from_json("CERT", short_id), EncodingError);

  for (Json bad : {Json(true), Json(1.5), Json(-1), Json("2000"), Json(9007199254740992ull)}) {
    Json j = transport("cert_v1");
    j["cap"] = bad;
    EXPECT_THROW(Object::from_json("CERT", j), EncodingError) << bad.dump();
  }

  Json bad_name = transport("mcert_pharmacy");
  bad_name["dn"] = "Pharmacy|Evil";
  EXPECT_THROW(Object::from_json("MCERT", bad_name), EncodingError);
}

TEST(Codec, SignatureMustBe64Bytes) {
  Json j = transport("tag_counter1");
  j["sig"] = b64u_encode(Bytes(63, 0x01));
  EXPECT_THROW(Object::from_json("TAG", j), EncodingError);
  j.erase("sig");
  Object unsigned_tag = Object::from_json("TAG", j);  // allowed, but verifies as false
  EXPECT_FALSE(unsigned_tag.sig().has_value());
  EXPECT_FALSE(unsigned_tag.verify(test::vector_pub("maya")));
}

TEST(Codec, DetIsUnsigned) {
  Json j = transport("det_pharmacy");
  j["sig"] = b64u_encode(Bytes(64, 0x01));
  EXPECT_THROW(Object::from_json("DET", j), EncodingError);
}

TEST(Dlog, BodyDependsOnKind) {
  Json accept = transport("dlog_accept");
  Dlog d(Object::from_json("DLOG", accept));
  EXPECT_EQ(d.kind(), "ACCEPT");
  EXPECT_TRUE(d.verify_self());
  EXPECT_THROW(d.contact_id(), std::logic_error);  // a CONTACT field on an ACCEPT entry

  Json wrong_kind = accept;
  wrong_kind["kd"] = "CONTACT";  // the ACCEPT body keys are now unknown, the CONTACT ones missing
  EXPECT_THROW(Object::from_json("DLOG", wrong_kind), EncodingError);
  wrong_kind["kd"] = "DELETE";
  EXPECT_THROW(Object::from_json("DLOG", wrong_kind), EncodingError);

  Json refuse = transport("dlog_refuse");
  refuse["ck"] = "C7";
  EXPECT_THROW(Object::from_json("DLOG", refuse), EncodingError);

  Json seq0 = accept;
  seq0["q"] = 0;
  EXPECT_THROW(Object::from_json("DLOG", seq0), EncodingError);
}

TEST(Dlog, ContactIdListsAreCapped) {
  Json contact = transport("dlog_contact_maya");
  contact["si"] = Json::array();
  for (int i = 0; i < 200; ++i) contact["si"].push_back(b64u_encode(Bytes(8, static_cast<std::uint8_t>(i))));
  EXPECT_NO_THROW(Object::from_json("DLOG", contact));
  contact["si"].push_back(b64u_encode(Bytes(8, 0xff)));
  EXPECT_THROW(Object::from_json("DLOG", contact), EncodingError);
}

TEST(Policy, MerchantLimits) {
  const Json& v = test::vector("objects", "policy");
  Policy p(Object::from_fields("POLICY", v.at("fields"), v.at("sig")));
  EXPECT_EQ(p.merchant_limit(test::hex("4d1785392a3969481fbc1235ee3056cd")), 1500);
  EXPECT_EQ(p.merchant_limit(test::hex("387e74021fac339dec4415daf54c1cc5")), 500);
  EXPECT_FALSE(p.merchant_limit(Bytes(16, 0)).has_value());
  EXPECT_TRUE(p.is_frozen(test::hex("3526ace1acc8a1382175177638f9ebfc")));

  for (const char* bad : {"4d1785392a3969481fbc1235ee3056cd:0150",  // leading zero
                          "4D1785392A3969481FBC1235EE3056CD:150",   // uppercase id
                          "4d1785392a3969481fbc1235ee3056cd:",      // no amount
                          "4d1785392a3969481fbc1235ee3056:150",     // short id
                          "4d1785392a3969481fbc1235ee3056cd:-1"}) {
    Json fields = v.at("fields");
    fields["merchant_limits"] = Json::array({bad});
    EXPECT_THROW(Object::from_fields("POLICY", fields, nullptr), EncodingError) << bad;
  }
  Json dup = v.at("fields");
  dup["merchant_limits"] = Json::array({"4d1785392a3969481fbc1235ee3056cd:1", "4d1785392a3969481fbc1235ee3056cd:2"});
  EXPECT_THROW(Object::from_fields("POLICY", dup, nullptr), EncodingError);
}

TEST(Policy, ListsAreSortedOnlyInTheCanonicalString) {
  const Json& v = test::vector("objects", "policy");
  Object o = Object::from_fields("POLICY", v.at("fields"), v.at("sig"));
  // The vector's lists are deliberately unsorted: to_fields keeps them as given.
  EXPECT_EQ(o.to_fields(), v.at("fields"));
  EXPECT_EQ(o.canonical(), test::str(v.at("canonical")));
}

TEST(Ids, PayAndTagShareAnId) {
  const Json& v = test::vector("pays", "pay_pharmacy");
  Pay p = Pay::from_vector(v);
  EXPECT_EQ(item_id(p), p.tag.tag_hash());
  EXPECT_EQ(item_id("TAG", p.tag.object()), item_id(p));
  EXPECT_THROW(item_id("CERT", p.tag.object()), EncodingError);  // kind must match the body
  EXPECT_THROW(item_id("PAY", p.tag.object()), EncodingError);
}

TEST(Ids, ContactIdIsTheSameFromBothSides) {
  Bytes a = test::vector_pub("maya"), b = test::vector_pub("gas_station");
  Bytes na(16, 0x01), nb(16, 0x02);
  EXPECT_EQ(contact_id(a, na, b, nb), contact_id(b, nb, a, na));
  EXPECT_NE(contact_id(a, na, b, nb), contact_id(a, nb, b, na));  // each nonce goes with its own pub
  EXPECT_THROW(contact_id(a, na, a, nb), EncodingError);
}

TEST(Ids, ProofIdIgnoresTagOrder) {
  Bytes x(32, 0x01), y(32, 0x02);
  EXPECT_EQ(proof_canonical(x, y), proof_canonical(y, x));
}

}  // namespace
}  // namespace stormcash
