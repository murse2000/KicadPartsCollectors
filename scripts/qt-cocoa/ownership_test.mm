#include <QApplication>
#include <QTableWidget>
#include <QAccessible>
#include <cstdio>
#import <AppKit/AppKit.h>
#import <objc/runtime.h>

@interface NSObject (QtOwnershipTest)
- (id)initWithId:(unsigned int)identifier role:(NSString *)role;
+ (id)elementWithInterface:(QAccessibleInterface *)iface;
@end

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QAccessible::setActive(true);
    QTableWidget table(2, 2);
    table.show();
    app.processEvents();
    auto *iface = QAccessible::queryAccessibleInterface(&table);
    auto axid = QAccessible::uniqueId(iface);
    Class cls = objc_getClass("QMacAccessibilityElement");
    if (!cls) return 2;
    // 합성 셀 해제 후에도 부모 표의 접근성 인터페이스는 살아 있어야 한다.
    id placeholder = [[cls alloc] initWithId:axid role:NSAccessibilityCellRole];
    [placeholder release];
    bool retained = QAccessible::accessibleInterface(axid) == iface;
    std::printf("parent interface retained: %s\n", retained ? "yes" : "NO");
    if (!retained) return 1;
    // 선택된 셀 조회와 표 재생성을 반복해 실제 충돌 경로를 검사한다.
    for (int cycle = 0; cycle < 40; ++cycle) {
        @autoreleasepool {
            table.setRowCount(0);
            table.setRowCount(2);
            table.setItem(0, 0, new QTableWidgetItem("part"));
            table.selectRow(0);
            app.processEvents();
            iface = QAccessible::queryAccessibleInterface(&table);
            if (!iface->selectionInterface() || iface->selectionInterface()->selectedItemCount() != 2)
                return 4;
            id element = [cls elementWithInterface:iface];
            [element accessibilityChildren];
            NSArray *selected = [element accessibilitySelectedChildren];
            if (!selected.count) return 3;
            app.processEvents();
        }
    }
    std::puts("selected cells and model reset: 40 cycles passed");
    return 0;
}
