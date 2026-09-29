# LiveLedger — phân ca đơn live TikTok trên từng máy

Mỗi người tải hoặc clone mã nguồn về **máy của mình** rồi chạy riêng. Mỗi bản cài có file SQLite riêng trong `data/tooltiktok.sqlite3`; sửa lịch hoặc nhập đơn trên máy A không tự thay dữ liệu máy B. GitHub chỉ chứa mã nguồn, không chứa dữ liệu đơn hàng. Khi cần chuyển trạng thái hoặc tái hiện lỗi, dùng **Thiết lập → Xuất dữ liệu JSON** rồi nhập file đó ở bản cài khác.

## Bắt đầu trên Windows

1. Cài Python 3.12 trở lên và tải/clone repository này vào một thư mục có quyền ghi.
2. Nhấp đúp `start-local.cmd`. Lần đầu cần Internet để cài Flask và Waitress; ứng dụng tạo thư mục `.venv` và `data` riêng trên máy này.
3. Ứng dụng tự chọn cổng trống từ 8001 đến 8099 rồi mở cửa sổ của nó (trên Windows có Edge, nó mở trong cửa sổ app riêng). Địa chỉ chính xác hiện trong cửa sổ chạy. Bạn vào thẳng ứng dụng, không cần tài khoản hay mật khẩu.
4. Giữ cửa sổ chạy ứng dụng mở khi sử dụng. Muốn dừng, đóng cửa sổ đó. Lần sau chỉ cần nhấp đúp `start-local.cmd`.

Nếu chép thư mục source từ máy khác, không cần chép `.venv/`: môi trường Python trong đó có thể trỏ tới đường dẫn chỉ tồn tại trên máy cũ. Bản `start-local.cmd` mới tự kiểm tra và tạo lại `.venv` khi Python trong đó không chạy được. Nếu máy chưa có Python 3.12+, hãy cài Python trước; nếu bước cài thư viện thất bại, xem lỗi `pip` hiển thị ngay phía trên thông báo cuối để phân biệt lỗi mạng, quyền ghi và đường dẫn.

Ứng dụng chỉ nghe trên `127.0.0.1`, tức chính máy này. Nó không gửi dữ liệu đến máy của người khác. `index.html` phải được mở qua địa chỉ trên; mở trực tiếp bằng `file://` hoặc GitHub Pages sẽ không kết nối được SQLite.

Khi cập nhật mã bằng `git pull`, thư mục `data/` và `.venv/` vẫn nằm trên máy và bị Git bỏ qua. Clone sang một thư mục/máy khác sẽ tạo cơ sở dữ liệu mới ở nơi đó. Không copy thư mục `data/` vào GitHub.

## Xuất dữ liệu để chuyển máy hoặc tái hiện lỗi

Trên máy có dữ liệu cần chuyển, vào **Thiết lập → Xuất dữ liệu JSON**. File gồm nhân viên, lịch cố định, lịch đổi ca, tỷ lệ hoa hồng, đơn hàng, gán tay và các kỳ đã chốt. Nó chứa mã đơn, tên sản phẩm và số tiền; chỉ chia sẻ với người được phép xem dữ liệu kinh doanh.

Ở bản cài khác, vào **Thiết lập → Nhập dữ liệu từ bản cài khác**, chọn file JSON và bấm **Xem trước**. Sau khi xác nhận, ứng dụng thay toàn bộ dữ liệu nghiệp vụ trên máy nhận bằng nội dung file. Ứng dụng tạo một bản sao lưu SQLite của máy nhận **trước khi thay**. Vì vậy có thể clone source vào một thư mục thử nghiệm, nhập file của người dùng và tái hiện lỗi mà không đụng cơ sở dữ liệu làm việc của họ.

Nếu chạy hai bản clone trên cùng một máy, mỗi bản tự chọn cổng còn trống và vẫn có `data/` riêng. Muốn dùng cổng cố định, chạy `start-local.cmd --port 8010` rồi mở `http://127.0.0.1:8010/`.

Xuất dữ liệu là thao tác thủ công. Các máy không đồng bộ tự động, và nhập cùng một file nhiều lần sẽ thay dữ liệu hiện tại bằng trạng thái trong file.

## Chuyển dữ liệu từ công cụ HTML cũ

1. Mở **đúng file HTML cũ ở đúng đường dẫn đã dùng trước đây** trong trình duyệt có dữ liệu. Vào **Thiết lập → Sao lưu dữ liệu** để tải JSON. Đổi đường dẫn file cũ có thể làm trình duyệt không thấy dữ liệu đã lưu. `legacy.html` trong repository chỉ là bản mã cũ để đối chiếu.
2. Trong LiveLedger trên máy cần dùng, vào **Thiết lập → Chuyển từ công cụ HTML cũ**, chọn JSON và xem trước. Có thể chọn thay lịch/tỷ lệ hoặc chỉ nhập đơn. Nếu khoảng lịch thứ ba ở bản cũ chưa lưu thành công, giữ lịch khởi tạo từ ảnh rồi kiểm tra từng khoảng trong **Lịch live**.
3. So sánh số đơn, lịch và báo cáo trước khi bỏ bản cũ. Mỗi máy có dữ liệu HTML cũ riêng thì xuất và chuyển riêng.

## Quy tắc đang dùng

- Gán đơn theo `Created Time` trong CSV. Giờ kết thúc không thuộc ca: HÀO 21:00–01:00 hôm sau nhận đơn 00:59:59, còn đơn 01:00:00 cần đối soát.
- Nhập CSV có bước xem trước số đơn mới, đơn cập nhật và dòng sai. File có dòng sai không được ghi. Công cụ chỉ lưu các cột cần tính, không lưu tên, số điện thoại hay địa chỉ khách trong CSV gốc.
- Lịch có thể chia thành các khoảng ngày. Giờ/phút chọn bằng danh sách 24 giờ và phải chọn rõ kết thúc **Hôm nay** hay **Hôm sau**. Khi ca của **hai nhân viên khác nhau** chồng giờ, app liệt kê các cặp trùng và hỏi xác nhận live chung. Chọn Không thì lịch chưa được lưu; chọn Có thì đơn tạo trong đúng phần giờ trùng được chia doanh thu 50/50. Mỗi người tính hoa hồng trên nửa doanh thu theo tỷ lệ riêng của mình. Báo cáo chia cả số đơn và số lượng sản phẩm theo 0,5 để tổng không bị đếm hai lần. Một nhân viên tự trùng ca hoặc ba người cùng trùng giờ vẫn bị chặn. Khoảng ngày chồng nhau cũng bị chặn; lịch riêng một ngày được ưu tiên hơn lịch cố định.
- Đơn ngoài LIVE hoặc hủy/hoàn không được tính hoa hồng. Đơn LIVE ngoài ca có thể gán tay kèm lý do; gán tay một đơn đang live chung sẽ chuyển toàn bộ doanh thu cho người được chọn. Tỷ lệ hoa hồng có ngày hiệu lực; kỳ đã chốt giữ bản kết quả cố định cho đến khi được mở lại có ghi lý do.
- Báo cáo hoa hồng là số tạm tính. Cần thống nhất quy tắc làm tròn và xử lý hoàn tiền thực tế trước khi dùng làm số chi trả cuối cùng.

## Sao lưu kỹ thuật

`data/tooltiktok.sqlite3` là dữ liệu làm việc; `data/.secret-key` giữ khóa cho phiên thao tác nội bộ. `data/backups/` chứa tối đa 30 bản SQLite gần nhất: một bản khi khởi động mỗi ngày và một bản trước khi nhập dữ liệu từ bản cài khác hoặc công cụ cũ. Có thể bấm **Sao lưu SQLite trên máy** để tạo thêm. Hãy chép file JSON hoặc bản SQLite sang ổ khác; bản sao nằm cùng ổ không bảo vệ khỏi hỏng ổ.

## Kiểm thử cho người phát triển

```powershell
python -m pip install -r requirements.txt pytest
python -m pytest -q
node --check app.js
```

Các kiểm thử bao phủ gán ca qua nửa đêm, xác nhận live chung và chia doanh thu, ngăn ba ca chồng giờ, nhập CSV, chốt kỳ và xuất/nhập dữ liệu sang một bản cài khác.
