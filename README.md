# Công cụ phân ca đơn live TikTok

Ứng dụng HTML độc lập để đối chiếu file CSV đơn hàng TikTok với lịch livestream theo ngày và tổng hợp sản phẩm, doanh số, hoa hồng theo nhân viên.

## Sử dụng

1. Mở `index.html` bằng Chrome hoặc Edge.
2. Chọn **Nhập CSV TikTok** để thêm hoặc cập nhật đơn hàng. Đơn được gán theo cột `Created Time`.
3. Mở **Lịch live** nếu cần đổi ca của một ngày cụ thể. Lịch riêng của ngày đó sẽ được ưu tiên so với lịch cố định.
4. Vào **Thiết lập** để nhập tỷ lệ hoa hồng và sao lưu dữ liệu.
5. Xem biểu đồ sản phẩm hoặc xuất CSV tổng hợp và chi tiết đơn.

Lịch cố định hiện tại được khai báo ngay trong `index.html`. Thứ Hai không có ca mặc định. Ca HÀO kết thúc lúc 24:00; đơn tạo từ 00:00 thuộc ngày hôm sau.

File CSV được xử lý trong trình duyệt. Ứng dụng chỉ lưu thông tin đơn và sản phẩm cần cho báo cáo, không lưu tên, số điện thoại hay địa chỉ khách hàng. Dữ liệu lưu tại trình duyệt và địa chỉ mở ứng dụng; hãy dùng **Sao lưu dữ liệu** trước khi đổi trình duyệt, chuyển từ file cục bộ sang một địa chỉ web, hoặc xóa dữ liệu trình duyệt.

Doanh số tạm tính lấy từ cột `SKU Subtotal After Discount`. Hoa hồng = doanh số tạm tính × tỷ lệ của nhân viên. Đơn có dấu hiệu hủy hoặc hoàn được đưa sang mục **Đơn cần xem**.
