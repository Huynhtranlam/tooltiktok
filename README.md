# Công cụ phân ca đơn live TikTok

Ứng dụng HTML độc lập để đối chiếu file CSV đơn hàng TikTok với lịch livestream theo ngày và tổng hợp sản phẩm, doanh số, hoa hồng theo nhân viên.

## Sử dụng

1. Mở `index.html` bằng Chrome hoặc Edge.
2. Chọn **Nhập CSV TikTok** để thêm hoặc cập nhật đơn hàng. Đơn được gán theo cột `Created Time`.
3. Mở **Lịch live** để thêm hoặc sửa các khoảng lịch cố định theo ngày bắt đầu/kết thúc. Nếu chỉ đổi ca một ngày, dùng **Lịch của một ngày**; lịch riêng được ưu tiên trong ngày đó.
4. Vào **Thiết lập** để nhập tỷ lệ hoa hồng và sao lưu dữ liệu.
5. Xem biểu đồ sản phẩm hoặc xuất CSV tổng hợp và chi tiết đơn.

Lịch cố định được lưu theo từng khoảng ngày trong trình duyệt và có thể chỉnh ở mục **Lịch live**. Đây là các **khung giờ quy đơn để tính GMV**, được chừa dư để bao phủ những hôm nhân viên bắt đầu hoặc kết thúc live lệch giờ; không phải thời lượng live thực tế của mỗi người. Hai khoảng ban đầu là:

- **01–20/09/2026:** Thứ Hai đến Chủ nhật, NHUNG 10:00–14:00, VY 15:00–19:00, HÀO 21:00–01:00 hôm sau.
- **21/09–10/10/2026:** Thứ Hai không có ca mặc định; thứ Ba đến Chủ nhật theo lịch mới trong ứng dụng (NHUNG 11:00–13:30, các ca chiều luân phiên VY/THƯ, PHÁT 19:00–21:30, HÀO 21:30–24:00).

Từ **11/10/2026** chưa có lịch cố định cho đến khi thêm khoảng mới. Các khoảng không được chồng ngày; ngày chưa có lịch sẽ đưa đơn vào mục cần xem. Khi thêm lịch mới, đơn cũ vẫn được đối chiếu với lịch của đúng khoảng ngày cũ. Đơn sau nửa đêm và trước 01:00 trong khung HÀO 21:00–01:00 của lịch cũ được gán cho HÀO; đúng 01:00 trở đi không thuộc khung này. Lịch riêng của từng ngày và gán đơn thủ công vẫn được ưu tiên. Dữ liệu đơn đã nhập được tính lại khi mở phiên bản mới; không cần nhập lại CSV.

File CSV được xử lý trong trình duyệt. Ứng dụng chỉ lưu thông tin đơn và sản phẩm cần cho báo cáo, không lưu tên, số điện thoại hay địa chỉ khách hàng. Dữ liệu lưu tại trình duyệt và địa chỉ mở ứng dụng; hãy dùng **Sao lưu dữ liệu** trước khi đổi trình duyệt, chuyển từ file cục bộ sang một địa chỉ web, hoặc xóa dữ liệu trình duyệt.

Doanh số tạm tính lấy từ cột `SKU Subtotal After Discount`. Hoa hồng = doanh số tạm tính × tỷ lệ của nhân viên. Đơn có dấu hiệu hủy hoặc hoàn được đưa sang mục **Đơn cần xem**.
