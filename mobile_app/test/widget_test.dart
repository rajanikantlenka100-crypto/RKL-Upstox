import 'package:flutter_test/flutter_test.dart';

import 'package:rkl_mobile/main.dart';

void main() {
  test('RKL app exposes the existing read-only root widget', () {
    expect(const RklApp(), isA<RklApp>());
  });

  test('RKL exposes exactly four supported terminal themes', () {
    expect(RklThemeId.values, hasLength(4));
    expect(RklThemeId.values, containsAll(const [
      RklThemeId.dark,
      RklThemeId.light,
      RklThemeId.pro,
      RklThemeId.neon,
    ]));
  });
}
