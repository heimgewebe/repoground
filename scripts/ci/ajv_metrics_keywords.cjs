"use strict";

module.exports = function addMetricsMetadataKeywords(ajv) {
  for (const keyword of ["x-producers", "x-consumers"]) {
    ajv.addKeyword({ keyword, schemaType: "array", valid: true });
  }
};
